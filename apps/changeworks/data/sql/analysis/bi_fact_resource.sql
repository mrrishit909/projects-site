-- P09-ART-06 fact: allocation against capacity, one row per resource x period that has an allocation: allocated (exact), capacity, headroom and an at-capacity flag (exactly at capacity is allowed; over capacity is refused). Needs no temporary table.
SELECT a.resource_id, a.period_index, sum(a.amount)::text AS allocated, r.capacity_per_period::text AS capacity, (r.capacity_per_period - sum(a.amount))::text AS headroom,
       (sum(a.amount) = r.capacity_per_period)::int AS at_capacity, (sum(a.amount) > r.capacity_per_period)::int AS over_capacity
FROM resource_allocations a JOIN resources r ON r.resource_id = a.resource_id
GROUP BY a.resource_id, a.period_index, r.capacity_per_period
ORDER BY a.resource_id COLLATE "C", a.period_index
