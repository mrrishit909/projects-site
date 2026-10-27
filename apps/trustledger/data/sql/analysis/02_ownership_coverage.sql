-- P07-ART-04 investigation 02: ownership coverage (D-02, DR-02, INJ-07): datasets whose accountable owner is ACTIVE at the as-of / datasets registered by it.
-- Question: who is accountable? An inactive owner leaves the dataset uncovered. Observed on the loaded snapshot at its as-of.

-- @@ summary
SELECT count(*) AS datasets, count(*) FILTER (WHERE covered) AS covered, count(*) FILTER (WHERE NOT covered) AS uncovered,
       round(count(*) FILTER (WHERE covered)::numeric / count(*), 6) AS coverage
FROM (SELECT d.dataset_id, (o.owner_id IS NOT NULL AND CASE WHEN o.deactivated_at IS NOT NULL THEN tl_p.as_of < o.deactivated_at ELSE o.active END) AS covered
      FROM datasets d LEFT JOIN owners o ON o.owner_id = d.owner_id, tl_p WHERE d.registered_at <= tl_p.as_of) x

-- @@ uncovered
-- The datasets with no accountable owner, the owner on record, when that owner was deactivated, and what the dataset still carries.
SELECT d.dataset_id, d.dataset_name, d.classification, d.monitored, d.owner_id, o.team AS owner_team, tl_iso(o.deactivated_at) AS owner_deactivated_at,
       (SELECT count(*) FROM tl_issue i WHERE i.dataset_id = d.dataset_id AND i.class <> 'resolved') AS unresolved_issues,
       (SELECT count(*) FROM tl_rules r WHERE r.dataset_id = d.dataset_id) AS active_rules
FROM datasets d JOIN owners o ON o.owner_id = d.owner_id, tl_p
WHERE d.registered_at <= tl_p.as_of AND NOT (CASE WHEN o.deactivated_at IS NOT NULL THEN tl_p.as_of < o.deactivated_at ELSE o.active END)
ORDER BY d.dataset_id COLLATE "C"

-- @@ by_team
-- Coverage by the owning team: which teams hold the gaps.
SELECT o.team, count(*) AS datasets, count(*) FILTER (WHERE o.active) AS covered, count(*) FILTER (WHERE NOT o.active) AS uncovered,
       round(count(*) FILTER (WHERE o.active)::numeric / count(*), 6) AS coverage
FROM datasets d JOIN owners o ON o.owner_id = d.owner_id, tl_p WHERE d.registered_at <= tl_p.as_of
GROUP BY o.team ORDER BY o.team COLLATE "C"

-- @@ inactive_owners
SELECT o.owner_id, o.owner_name, o.team, tl_iso(o.deactivated_at) AS deactivated_at, count(d.dataset_id) AS datasets_owned,
       (SELECT count(*) FROM tl_issue i WHERE i.owner_id = o.owner_id AND i.class <> 'resolved') AS unresolved_issues_assigned
FROM owners o LEFT JOIN datasets d ON d.owner_id = o.owner_id WHERE NOT o.active GROUP BY o.owner_id, o.owner_name, o.team, o.deactivated_at ORDER BY o.owner_id COLLATE "C"
