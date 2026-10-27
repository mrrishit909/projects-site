-- P09-ART-04 investigation 09: dependency delays, the refused cycle, the shared specialist at capacity and the three initiatives flagged DEPLOYMENT_BEFORE_FEASIBLE_START (D-03, D-05 D-P9-08, D-P9-15,
-- D-09 R9-06, DR-05, INJ-07, INJ-09, P09-TEST-07, P09-TEST-09).
-- Question: can the roadmap be delivered in the order and with the people the plan assumes? Feasible start = the longest chain of (the prerequisite's feasible start, plus its duration for a
-- finish_to_start dependency, plus the lag), never earlier than the requested start; the delay is feasible minus requested and is never negative; the first dependency by id binds a tie. A cycle among
-- initiatives is refused (DEPENDENCY_CYCLE, listed from the rejected edge's initiative). A resource may be allocated up to its capacity (exactly at capacity is allowed); the allocation that would cross it
-- is refused RESOURCE_OVERALLOCATED with its period. The roadmap is reported beside the cash flows and does not re-time them: an initiative whose deployment_period is earlier than its feasible start
-- books benefits before the work can begin (DEPLOYMENT_BEFORE_FEASIBLE_START). Scope: the 24 initiatives, 40 dependencies, 8 resources and 557 allocations as loaded.

-- @@ dependency_delay
SELECT r.initiative_id, r.requested_start, r.duration_periods, r.feasible_start AS dependency_feasible_start, r.delay AS dependency_delay, r.binding_dependency_id,
       r.feasible_start + r.duration_periods AS finish, r.deployment_period, (r.deployment_period < r.feasible_start) AS deployment_before_feasible_start
FROM cw_roadmap r
ORDER BY r.initiative_id COLLATE "C"

-- @@ delay_summary
SELECT count(*) AS initiatives, count(*) FILTER (WHERE r.delay > 0) AS delayed, count(*) FILTER (WHERE r.delay = 0) AS not_delayed, max(r.delay) AS longest_delay,
       (SELECT count(*) FROM dependencies) AS dependencies, (SELECT count(*) FROM dependencies d WHERE d.dependency_type = 'finish_to_start') AS finish_to_start,
       (SELECT count(*) FROM dependencies d WHERE d.dependency_type = 'start_to_start') AS start_to_start,
       count(*) FILTER (WHERE r.delay > 0 AND r.binding_dependency_id IS NULL) AS delayed_without_a_binding_dependency
FROM cw_roadmap r

-- @@ deployment_before_feasible_start
SELECT r.initiative_id, r.deployment_period, r.feasible_start AS dependency_feasible_start, r.feasible_start - r.deployment_period AS periods_early, r.binding_dependency_id
FROM cw_roadmap r WHERE r.deployment_period < r.feasible_start
ORDER BY r.initiative_id COLLATE "C"

-- @@ cycle_check
-- The 40 stored dependencies form no cycle: a walk along them from every initiative that revisits an initiative on its own path finds nothing.
WITH RECURSIVE walk(origin, at, path, cyclic) AS (
    SELECT d.prerequisite_id, d.initiative_id, ARRAY[d.prerequisite_id, d.initiative_id]::text[], d.prerequisite_id = d.initiative_id FROM dependencies d
    UNION ALL
    SELECT w.origin, d.initiative_id, w.path || d.initiative_id, d.initiative_id = ANY (w.path)
    FROM walk w JOIN dependencies d ON d.prerequisite_id = w.at WHERE NOT w.cyclic AND cardinality(w.path) < 40)
SELECT (SELECT count(*) FROM dependencies) AS dependencies, count(*) AS paths_walked, count(*) FILTER (WHERE cyclic) AS cycles_found,
       (SELECT count(*) FROM dependencies d WHERE d.initiative_id = d.prerequisite_id) AS self_dependencies, max(cardinality(path)) AS longest_chain_of_initiatives
FROM walk

-- @@ refused_cycle
-- INJ-07 / EV-07: init-001 is asked to depend on init-004 (edge d-inj-07). The stored graph already has the opposite path: init-004 depends on init-001 (d-003), so the new edge would close
-- init-001 -> init-004 -> init-001. The edge is typed here from the replay event; it is not in any table.
WITH RECURSIVE proposed(initiative_id, prerequisite_id) AS (VALUES ('init-001'::text, 'init-004'::text)),
walk(at, path, edges) AS (
    SELECT d.initiative_id, ARRAY[d.prerequisite_id, d.initiative_id]::text[], ARRAY[d.dependency_id]::text[]
    FROM dependencies d JOIN proposed p ON d.prerequisite_id = p.initiative_id
    UNION ALL
    SELECT d.initiative_id, w.path || d.initiative_id, w.edges || d.dependency_id
    FROM walk w JOIN dependencies d ON d.prerequisite_id = w.at WHERE cardinality(w.path) < 40)
SELECT p.initiative_id AS rejected_edge_initiative, p.prerequisite_id AS rejected_edge_prerequisite,
       array_to_string(ARRAY[p.initiative_id] || ARRAY(SELECT u.x FROM unnest(w.path) WITH ORDINALITY AS u(x, n) ORDER BY u.n DESC), ' -> ') AS cycle_it_would_close, array_to_string(w.edges, ',') AS stored_edges_on_the_path
FROM proposed p JOIN walk w ON w.at = p.prerequisite_id
ORDER BY cardinality(w.path), array_to_string(w.path, ',') COLLATE "C"
LIMIT 1

-- @@ resource_at_capacity
-- The shared specialist res-03 (2.00 FTE) is allocated to its full capacity in periods 12..16: allocated, headroom 0.00, and nothing over capacity is stored.
SELECT a.resource_id, r.capacity_per_period::numeric(20,2) AS capacity, a.period_index, round(sum(a.amount), 2) AS allocated, round(r.capacity_per_period - sum(a.amount), 2) AS headroom,
       string_agg(DISTINCT a.initiative_id COLLATE "C", ',' ORDER BY a.initiative_id COLLATE "C") AS initiatives
FROM resource_allocations a JOIN resources r ON r.resource_id = a.resource_id
WHERE a.resource_id = 'res-03'
GROUP BY a.resource_id, r.capacity_per_period, a.period_index
HAVING sum(a.amount) >= r.capacity_per_period
ORDER BY a.period_index

-- @@ resources
SELECT r.resource_id, r.name, r.capacity_per_period::numeric(20,2) AS capacity, r.unit,
       (SELECT count(*) FROM resource_allocations a WHERE a.resource_id = r.resource_id) AS allocation_rows,
       (SELECT count(*) FROM (SELECT a.period_index FROM resource_allocations a WHERE a.resource_id = r.resource_id GROUP BY a.period_index HAVING sum(a.amount) = r.capacity_per_period) x) AS periods_exactly_at_capacity,
       (SELECT count(*) FROM (SELECT a.period_index FROM resource_allocations a WHERE a.resource_id = r.resource_id GROUP BY a.period_index HAVING sum(a.amount) > r.capacity_per_period) x) AS periods_over_capacity,
       (SELECT min(x.period_index) FROM (SELECT a.period_index FROM resource_allocations a WHERE a.resource_id = r.resource_id GROUP BY a.period_index HAVING sum(a.amount) = r.capacity_per_period) x) AS first_period_at_capacity,
       (SELECT max(x.period_index) FROM (SELECT a.period_index FROM resource_allocations a WHERE a.resource_id = r.resource_id GROUP BY a.period_index HAVING sum(a.amount) = r.capacity_per_period) x) AS last_period_at_capacity
FROM resources r
ORDER BY r.resource_id COLLATE "C"

-- @@ refused_requests
-- INJ-09 / EV-09: init-012 asks for 0.50 FTE more of res-03 in periods 14, 15 and 16. Each would take the sum past capacity, so each is refused RESOURCE_OVERALLOCATED; a sum equal to capacity is allowed.
-- The three requests are typed here from the replay event; they are not in any table.
WITH req(resource_id, initiative_id, period_index, requested) AS (VALUES ('res-03'::text, 'init-012'::text, 14, 0.50::numeric), ('res-03', 'init-012', 15, 0.50), ('res-03', 'init-012', 16, 0.50))
SELECT q.resource_id, q.initiative_id, q.period_index, q.requested::numeric(20,2) AS requested, round(coalesce(s.allocated, 0), 2) AS allocated_before, r.capacity_per_period::numeric(20,2) AS capacity,
       round(coalesce(s.allocated, 0) + q.requested, 2) AS would_be, (coalesce(s.allocated, 0) + q.requested > r.capacity_per_period) AS refused_overallocated
FROM req q JOIN resources r ON r.resource_id = q.resource_id
LEFT JOIN (SELECT a.resource_id, a.period_index, sum(a.amount) AS allocated FROM resource_allocations a GROUP BY a.resource_id, a.period_index) s ON s.resource_id = q.resource_id AND s.period_index = q.period_index
ORDER BY q.period_index
