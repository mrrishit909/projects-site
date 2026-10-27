-- P08-ART-04 investigation 05: the publication pointer history and the runs that never moved it (D-02, D-P8-08, P08-FLOW-05/06, P08-TEST-07, DR-02): the pointer moves only to the
-- publication of a run that succeeded AND passed its gate; a blocked run, and a run that failed before the gate, publish nothing and leave the pointer where it was.
-- Question: when a run fails, what do readers of the published dataset see?
-- SCOPE. complete world: runs, publications, quality results and the pointer are published in full.

-- @@ summary
-- One pointer, one row. Every publication belongs to a successful run with an allowed gate; the pointer rests on the publication of the latest successful run.
SELECT (SELECT count(*) FROM po_run) AS runs, (SELECT count(*) FROM publications) AS publications, (SELECT count(*) FROM po_run WHERE published) AS runs_that_moved_the_pointer,
       (SELECT count(*) FROM po_run WHERE NOT published) AS runs_that_left_it,
       (SELECT publication_id FROM publication_pointer WHERE id = 1) AS pointer,
       (SELECT run_id FROM publications WHERE publication_id = (SELECT publication_id FROM publication_pointer WHERE id = 1)) AS pointer_run,
       (SELECT publication_id FROM publications ORDER BY published_at DESC, publication_id COLLATE "C" DESC LIMIT 1) AS latest_publication,
       (SELECT count(*) FROM publications p JOIN po_run r ON r.run_id = p.run_id WHERE r.status <> 'success' OR r.gate_decision <> 'allowed') AS publications_of_failed_or_blocked_runs,
       to_char((SELECT min(published_at) FROM publications) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS first_published_at,
       to_char((SELECT max(published_at) FROM publications) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS last_published_at

-- @@ unmoved_runs
-- The 25 runs that never moved the pointer: where each stopped, what failed, the pointer before and after (the publication of the latest run that started no later), the
-- incident it opened and whether it published anything. The pointer after equals the pointer before in every row: that is the property.
SELECT r.run_id, to_char(r.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at, r.stage, r.failure_kind,
       (SELECT g.rule_name FROM po_gate_result g WHERE g.run_id = r.run_id AND g.severity = 'critical' AND g.failure_count > 0 ORDER BY g.rule_name COLLATE "C" LIMIT 1) AS failed_critical_check,
       before.publication_id AS pointer_before, after.publication_id AS pointer_after, before.publication_id = after.publication_id AS pointer_unchanged, r.published AS publication_exists,
       i.incident_id
FROM po_run r
LEFT JOIN LATERAL (SELECT p.publication_id FROM publications p JOIN pipeline_runs x ON x.run_id = p.run_id WHERE x.started_at < r.started_at ORDER BY x.started_at DESC LIMIT 1) before ON true
LEFT JOIN LATERAL (SELECT p.publication_id FROM publications p JOIN pipeline_runs x ON x.run_id = p.run_id WHERE x.started_at <= r.started_at ORDER BY x.started_at DESC LIMIT 1) after ON true
LEFT JOIN incidents i ON i.run_id = r.run_id
WHERE NOT r.published ORDER BY r.started_at, r.run_id COLLATE "C"

-- @@ designed_blocked_run
-- DR-02, the designated run of P08-TEST-07: the second run in time order that failed on relationships_intact. It was blocked by one orphan output row, published nothing, left the
-- pointer on the previous publication, opened an incident and was recovered by the next verified run.
SELECT x.run_id, x.failure_kind, g.eligible_count AS relationships_eligible, g.failure_count AS relationships_failed, x.gate_decision,
       before.publication_id AS pointer_before, after.publication_id AS pointer_after, x.published AS publication_exists, i.incident_id, i.recovery_run_id,
       to_char(i.opened_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at
FROM (SELECT r.*, row_number() OVER (ORDER BY r.started_at, r.run_id COLLATE "C") AS n FROM po_run r WHERE r.failure_kind = 'relationships') x
JOIN po_gate_result g ON g.run_id = x.run_id AND g.rule_name = 'relationships_intact'
LEFT JOIN LATERAL (SELECT p.publication_id FROM publications p JOIN pipeline_runs y ON y.run_id = p.run_id WHERE y.started_at < x.started_at ORDER BY y.started_at DESC LIMIT 1) before ON true
LEFT JOIN LATERAL (SELECT p.publication_id FROM publications p JOIN pipeline_runs y ON y.run_id = p.run_id WHERE y.started_at <= x.started_at ORDER BY y.started_at DESC LIMIT 1) after ON true
LEFT JOIN incidents i ON i.run_id = x.run_id
WHERE x.n = 2

-- @@ pointer_staleness
-- How long the pointer rested on an older publication because a run failed: for each unmoved run, the seconds from the pointer's publication to the next publication that moved it.
SELECT count(*) AS unmoved_runs, min(s.seconds) AS min_seconds, max(s.seconds) AS max_seconds, round(avg(s.seconds) / 60, 4) AS mean_minutes
FROM (SELECT r.run_id, floor(extract(epoch FROM nxt.published_at - cur.published_at))::bigint AS seconds
      FROM po_run r
      JOIN LATERAL (SELECT p.published_at FROM publications p JOIN pipeline_runs x ON x.run_id = p.run_id WHERE x.started_at < r.started_at ORDER BY x.started_at DESC LIMIT 1) cur ON true
      JOIN LATERAL (SELECT p.published_at FROM publications p JOIN pipeline_runs x ON x.run_id = p.run_id WHERE x.started_at > r.started_at ORDER BY x.started_at LIMIT 1) nxt ON true
      WHERE NOT r.published) s
