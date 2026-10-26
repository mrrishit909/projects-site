-- 09: the golden case's per-case hours from the multirange method of 00 (P02-GOLD-01, P02-ART-04).
-- Run against a database seeded with tests/fixtures/golden/inputs.json (prepare_snapshot.py --golden). The expected
-- values are hand-derived in tests/fixtures/golden/CALCULATION.md: calendar 66, business 2, paused 65 (business overlap 1),
-- active 1 with the pause eligible, 2 with it not eligible. Against the generated snapshot there is no 'case-001': 0 rows.
SELECT case_id,
       round(calendar_s / 3600, 4)                           AS calendar_h,
       round(business_s / 3600, 4)                           AS business_h,
       round(paused_s / 3600, 4)                             AS paused_h,
       round(paused_business_s / 3600, 4)                    AS paused_business_overlap_h,
       round(active_s / 3600, 4)                             AS active_h_pause_eligible,
       round(business_s / 3600, 4)                           AS active_h_pause_not_eligible,
       within_sla
  FROM os_case_facts
 WHERE case_id = 'case-001';
