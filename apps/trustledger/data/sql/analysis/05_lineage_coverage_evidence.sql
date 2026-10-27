-- P07-ART-04 investigation 05: lineage coverage and the three evidence kinds (D-02, INJ-08).
-- Observed lineage coverage = DISTINCT observed (source, target) pairs that match a declared pair / declared pairs. Inferred edges are never presented as observed and
-- never enter the numerator; observed pairs with no declared counterpart are listed as undeclared. Observed on the loaded snapshot at its as-of.

-- @@ evidence_kinds
-- One row per evidence kind: edge rows, distinct pairs, and how many rows carry an observation instant (observed <=> an instant is present, D-08).
SELECT e.evidence_type, count(*) AS edge_rows, count(DISTINCT (e.source_dataset_id, e.target_dataset_id)) AS distinct_pairs, count(e.observed_at) AS rows_with_observed_at
FROM lineage_edges e, tl_p WHERE e.observed_at IS NULL OR e.observed_at <= tl_p.as_of
GROUP BY e.evidence_type ORDER BY CASE e.evidence_type WHEN 'declared' THEN 1 WHEN 'observed' THEN 2 ELSE 3 END

-- @@ coverage
WITH le AS (SELECT e.* FROM lineage_edges e, tl_p WHERE e.observed_at IS NULL OR e.observed_at <= tl_p.as_of),
dec AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'declared'),
obs AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'observed'),
inf AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'inferred')
SELECT (SELECT count(*) FROM dec) AS declared_pairs, (SELECT count(*) FROM obs) AS observed_pairs,
       (SELECT count(*) FROM dec JOIN obs USING (s, t)) AS observed_matching_declared,
       round((SELECT count(*) FROM dec JOIN obs USING (s, t))::numeric / (SELECT count(*) FROM dec), 6) AS coverage,
       (SELECT count(*) FROM obs WHERE NOT EXISTS (SELECT 1 FROM dec WHERE dec.s = obs.s AND dec.t = obs.t)) AS undeclared_observed,
       (SELECT count(*) FROM dec WHERE NOT EXISTS (SELECT 1 FROM obs WHERE dec.s = obs.s AND dec.t = obs.t)) AS declared_not_observed,
       (SELECT count(*) FROM inf) AS inferred_pairs,
       (SELECT count(*) FROM inf WHERE EXISTS (SELECT 1 FROM dec WHERE dec.s = inf.s AND dec.t = inf.t) AND NOT EXISTS (SELECT 1 FROM obs WHERE obs.s = inf.s AND obs.t = inf.t)) AS inferred_on_declared_unobserved,
       (SELECT count(*) FROM inf WHERE EXISTS (SELECT 1 FROM obs WHERE obs.s = inf.s AND obs.t = inf.t)) AS inferred_also_observed

-- @@ undeclared_observed
-- Data moves along these paths and nobody declared them.
WITH le AS (SELECT e.* FROM lineage_edges e, tl_p WHERE e.observed_at IS NULL OR e.observed_at <= tl_p.as_of),
dec AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'declared'),
obs AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'observed')
SELECT obs.s AS source_dataset_id, obs.t AS target_dataset_id FROM obs WHERE NOT EXISTS (SELECT 1 FROM dec WHERE dec.s = obs.s AND dec.t = obs.t) ORDER BY obs.s COLLATE "C", obs.t COLLATE "C"

-- @@ declared_not_observed
-- Declared but never seen moving: either dead documentation or an observation gap. Each row says whether an inferred edge covers the pair (and is NOT counted).
WITH le AS (SELECT e.* FROM lineage_edges e, tl_p WHERE e.observed_at IS NULL OR e.observed_at <= tl_p.as_of),
dec AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'declared'),
obs AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'observed'),
inf AS (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM le WHERE evidence_type = 'inferred')
SELECT dec.s AS source_dataset_id, dec.t AS target_dataset_id, EXISTS (SELECT 1 FROM inf WHERE inf.s = dec.s AND inf.t = dec.t) AS an_inferred_edge_covers_it
FROM dec WHERE NOT EXISTS (SELECT 1 FROM obs WHERE dec.s = obs.s AND dec.t = obs.t) ORDER BY dec.s COLLATE "C", dec.t COLLATE "C"

-- @@ inferred
SELECT inf.s AS source_dataset_id, inf.t AS target_dataset_id,
       EXISTS (SELECT 1 FROM lineage_edges d WHERE d.evidence_type = 'declared' AND d.source_dataset_id = inf.s AND d.target_dataset_id = inf.t) AS declared,
       EXISTS (SELECT 1 FROM lineage_edges o WHERE o.evidence_type = 'observed' AND o.source_dataset_id = inf.s AND o.target_dataset_id = inf.t) AS observed
FROM (SELECT DISTINCT source_dataset_id s, target_dataset_id t FROM lineage_edges WHERE evidence_type = 'inferred') inf ORDER BY inf.s COLLATE "C", inf.t COLLATE "C"
