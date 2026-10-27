-- P07-ART-06 fact: one row per lineage edge (160) with its evidence kind and whether its (source, target) pair is declared and/or observed. Coverage = observed rows whose
-- pair is declared / declared rows; an inferred row is never observed.
SELECT e.edge_id, e.source_dataset_id, e.target_dataset_id, e.evidence_type, coalesce(tl_iso(e.observed_at), '') AS observed_at,
       EXISTS (SELECT 1 FROM lineage_edges x WHERE x.evidence_type = 'declared' AND x.source_dataset_id = e.source_dataset_id AND x.target_dataset_id = e.target_dataset_id)::int AS pair_declared,
       EXISTS (SELECT 1 FROM lineage_edges x WHERE x.evidence_type = 'observed' AND x.source_dataset_id = e.source_dataset_id AND x.target_dataset_id = e.target_dataset_id)::int AS pair_observed
FROM lineage_edges e, tl_p WHERE e.observed_at IS NULL OR e.observed_at <= tl_p.as_of ORDER BY e.edge_id COLLATE "C"
