# ChangeWorks — synthetic data generator specification (P09-WORK-03)

* Seed 20261026; monthly periods 2026-01 .. 2028-12 (36 periods, `period_basis` monthly, discount rates declared
  annual and converted per D-01), `as_of` 2026-10-05T00:00:00Z; 24 initiatives in 4 programmes with sponsors and
  statuses; 30 process baselines over two approved versions; about 160 assumption versions; about 900 cost items
  (one-time and expanded recurring) and about 700 benefit items across the four classes with ramps and lags; 40
  dependencies; 8 shared resources with allocations; 60 stakeholder groups with impact mappings; 300 readiness
  assessments; 500 adoption observations and 200 training completions; 400 benefit observations with baseline
  trends; 120 risk items; 30 scenario versions and 12 forecast versions; the demo profile of section 12.
* Designed relationships: one initiative whose only benefit is released capacity (no cash case without a
  conversion); two initiatives claiming the same released capacity; one initiative that never pays back; one
  forecast revised twice after a missed target with the original kept; one shared specialist overallocated in three
  periods; one observed improvement that is mostly the baseline trend; adoption that lags training completion by
  several periods.
* Injected defects (manifest + replay events, one per P09-TEST-01..12): time savings booked as cash without a
  staffing change, two initiatives claiming the same capacity, an annual rate applied monthly, a benefit before
  deployment, training completion substituted for adoption, a forecast overwrite, a dependency cycle, a
  never-paying-back case presented with a payback, an overallocated specialist, an improvement attributed entirely
  to the rollout, a one-time cost recurring, cost avoidance added to realised cash savings.
* Output under 5 MB; disclose every outcome-informed choice; the synthetic counterfactual (true benefit share) lives
  only in the manifest.
